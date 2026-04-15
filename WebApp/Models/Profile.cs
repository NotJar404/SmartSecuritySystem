using Microsoft.AspNetCore.Http;

namespace WebApp.Models
{
    public class Profile
    {
        public int Id { get; set; }

        // =========================
        // USER INFORMATION
        // =========================
        public string FullName { get; set; } = string.Empty;

        public string Username { get; set; } = string.Empty;

        public string Email { get; set; } = string.Empty;

        public string Role { get; set; } = string.Empty;

        // =========================
        // PROFILE IMAGE
        // =========================
        public string ProfileImagePath { get; set; } = "/images/default-profile.png";

        public IFormFile? ProfileImage { get; set; }

        // =========================
        // CONSTRUCTORS
        // =========================
        public Profile() { }

        public Profile(int id, string fullName, string username, string email, string role)
        {
            Id = id;
            FullName = fullName;
            Username = username;
            Email = email;
            Role = role;
        }
    }
}